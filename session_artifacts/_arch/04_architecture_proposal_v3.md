# Architecture Proposal v3 — rawdata → analyzer → console pipeline (Wave 2 v3 iteration)

> Wave 2 v3 deliverable from `arch-designer` (running on general-purpose harness; self-constrained to designer role). **Focused revision of v2**, NOT a full rewrite.
>
> Changes vs v2:
> - **§1** rewritten per addendum v3 §1 + §6 — operator-diagnostic framing (Console is 策划's diagnostic tool, not internal correctness checker)
> - **§5.5** adds (a) `console_diagnostic_complete` per-machine completeness flag replacing numeric `fallback_share_pct_max` threshold; (b) explicit 1-paragraph variant justification for `inherits_from`; (c) eager-cascade documentation for variants; (d) enumeration of fields that support `per_mode_overrides`
> - **§6** moves RTP integrity gate code construction to Phase 2 (was Phase 5) — resolves Phase 2/Phase 5 circular dependency; Phase 5 simplifies to "flip default policy for `console_diagnostic_complete: true` machines from warn to error"
> - **§9** rewritten entirely — operator-diagnostic framing + adds **Layer 4** per-SpinType attribution self-consistency check (catches within-pid mis-attribution that v2's Layers 1-3 missed); per-machine `console_diagnostic_complete` semantics; restructured error format with per-layer cause + actionable hints
> - **§9.7** marked "Illustrative, not exhaustive — comprehensive list maintained by QA team"
>
> Reuses unchanged from v2 (validated by Wave 3 v2):
> - Manifest schema baseline (per-machine .json with analyzer_features list)
> - Plugin Protocol surface (3-class taxonomy + `AnalyzerFeature.REQUIRES` topological dependency + `feature_registry.ALL_FEATURES`)
> - Hash composition algorithm: `sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12]`
> - 6-phase migration framework
> - Per-class blast table replacing "10× headline"
>
> **Date**: 2026-05-15
> **Brief**: `00_brief.md` + `00_brief_v2_addendum.md` + `00_brief_v3_addendum.md` (the v3 addendum supersedes specific points)
> **v2**: `04_architecture_proposal_v2.md` (1490 lines)
> **v2 reviews**: `05_critique_v2.md` (6 blockers; 3 resolved by user via clarification; 3 addressed by this v3) + `06_validation_v2.md` (APPROVE + 2 minor doc gaps)
> **Coordinator summary**: `07_decision_v2.md`
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Problem statement (rewritten per addendum v3 §1 + §6 — operator-diagnostic framing)

### §1.1 The operator-diagnostic premise

The production console exists to serve a single, specific person: the **operator (策划)** who configures slot machines for the production fleet. The operator picks paytable values, weights, feature parameters, and RTP targets, then ships the resulting configuration to production. The machine code itself is **not** the source of error — production machines faithfully execute whatever the operator configured. The **rawdata** captured from production reflects exactly what the configuration produced, which **may be off-target if the operator misconfigured something** (a typo in a weight, wrong RTP target, mismatched paytable rows, etc.).

User's exact framing (from addendum v3 §1, verbatim):

> "console 的诉求是帮我分析真机数据,找到问题并优化,所以 console 必须要是正确的,真机数据是有可能存在错误的。包括刚刚我说的 rtp 报错,也是 console 认为分析不出机器的 rtp 报错。"

> "rawdata 错的意思不是机台的逻辑和数据错误,就是比如策划 rtp 配错了,手滑了,之类的。"

The console's job, therefore, is **not** to certify the machine produced "correct" RTP in some absolute sense. The operator owns the configuration. The console's job is to **analyze the rawdata correctly so it can tell the operator whether the configuration produced the intended result**. When the operator looks at a console report and sees RTP, payout distribution, hit rates, or per-SpinType attribution, those numbers must be the actual analysis of rawdata — not a synthesized estimate, not a silent fallback, not a "we couldn't tell so we made one up".

This is the load-bearing inversion vs v2's framing:

| Aspect | v2 (incorrect) | v3 (corrected per addendum) |
|---|---|---|
| What "RTP error" means | Internal analyzer bug | Console claims it cannot reliably analyze this machine right now |
| What console is | An internal correctness checker | A diagnostic tool for the operator |
| What "correctness" means | RTP statistically matches a target | Console's logic accurately reflects rawdata into the report |
| What happens when console can't analyze | Silent fallback to a synthesized number (today's `_unattributed_st<N>`) | Explicit per-machine error with actionable diagnosis hints |
| Who owns "machine RTP is wrong" | Console (which would auto-fix or warn) | **Operator** (who debugs their own configuration) |

The architecture's purpose, rewritten per this framing:

> **The architecture must deliver per-machine, accurate-or-explicitly-error diagnostic signals to the operator across 421+ machines, while supporting cheap addition of new machines / new features without invalidating unrelated reports.**

"Accurate" means: the console's logic must be correct so its signals are trustworthy. "Explicitly-error" means: when the console cannot reliably analyze a machine (e.g., the rules for its mechanic haven't been written, the rawdata has corruption, or the operator's configuration interacts with an unrecognized edge case), the console must say so with an actionable error message — not silently emit wrong numbers.

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

`console correct ∧ machine configured correctly → RTP signal trustworthy.` The console must be correct so its signals are trustworthy. Console-correctness is the precondition for the whole architecture's diagnostic value.

### §1.2 Five concrete pain points (each cited from Wave 1)

These are the same 5 pain points v2 named (the structural rot is unchanged); v3 keeps them but reframes how the proposal resolves them under the operator-diagnostic lens. Pain point #6 (silent fallback-bucket RTP leak) is upgraded to a top-level constraint with a different framing per §9.

1. **Universal `analyzer_version` stamp invalidates 1007 (machine, mode) pairs on any byte change** —
   `compute_analyzer_version()` at `fresh_slotlab/player_impact_analyzer.py:2141` SHA256s the entire 8,176-line file. Per `03 §3.3` live DB measurement, 2030 completed runs across 1007 distinct (machine, mode) pairs get flagged `stale_analyzer` by `/api/reports/stale-count` on any comment-only edit. **v3 framing**: this damages operator trust because reports they were debugging suddenly say "stale" when nothing semantically changed. **v3 fix**: per-machine `effective_analyzer_version` composed from base hash + feature hashes the machine declares (§4).

2. **Schema renames silently break 17 frontend renderers** — `03 §4.3` tabulates ~30 schema fields × 17 renderers. **v3 framing**: a silent renderer break shows the operator stale or wrong numbers — direct violation of "accurate-or-explicitly-error". **v3 fix**: explicit `SCHEMA_VERSION` per feature + frontend renderer registry with declared fallback rules (§5.3 + §5.4).

3. **Real-fleet hash is upstream, virtual hash is local** — `03 §3.4` measured 421 entries in `configs/machines.json` get `codeSummaryMd5` from upstream `/MachineConfigMd5`; `compute_code_md5(machine_name)` only feeds 6 virtual entries. **v3 stance**: preserved (out of scope per addendum §3).

4. **Duplication concentrated in md5 + summary-patch + session-CI + inference triggers** — `01 §4` itemizes six duplications. **v3 fix**: Phase 1 extracts ALL SIX (covered by v2 Phase 1; v3 keeps the same).

5. **Module globals + import-time side effects are latent suicide bombs** — `03 §4.1` enumerates 11 references to `RAWDATA_ROOT`, 33 module globals in the analyzer. Memory `feedback_subprocess_import_suicide_and_module_globals.md`. **v3 fix**: Phase 1 dependency injection (covered by v2).

### §1.3 The §9 framing change — operator diagnostic, not internal assertion

Memory `feedback_invariant_with_fallback_hides_drift.md` measured fleet-wide: 55 of 117 cached BCM (m, mode) pairs have >0.5% RTP falling into `_unattributed_st<N>` fallback buckets (M250 100%, M268/M260/M264 70-90%, M163/M147 ~35%). v2 framed this as an "internal RTP correctness" problem and built a 3-layer gate with a numeric threshold. **v3 reframes**: the fallback bucket is the symptom that the **console couldn't analyze this machine**. The architectural response is not "is RTP correct? fail if not", but **"can the console deliver a trustworthy signal to the operator? if not, say so explicitly with actionable diagnosis"**.

The reframe matters for two design decisions:

- The check is no longer a threshold gate (statistical noise can trip a threshold); it's a per-machine **completeness declaration** (operator-side concept; see §5.5 / §9).
- The check has 4 layers in v3 (was 3 in v2), with the new **Layer 4** catching within-pid attribution drift between SpinTypes — the mis-attribution case v2's 3 layers missed (Critic v2 Concern 2 / Q2; addendum v3 §2 must-resolve #2).

### §1.4 Headline blast-radius framing (per addendum v2 §1.1, kept from v2)

v2 replaced v1's "10× reduction" headline with a per-change-class blast table. v3 keeps the table unchanged — the framing is correct.

| Change class | Blast under current architecture | Blast under proposal | Reduction |
|---|---|---|---|
| **Per-cluster feature edit** (e.g., adding BCM cleanup rule) | 421 machines | 12-30 machines (one cluster) | 12-30× |
| **Per-machine bespoke fix** (e.g., M21 Buffalo-counter tweak) | 421 machines | 1 machine | 421× |
| **Novel machine onboarding** (M400 with new feature plugin) | 421 machines | 1 machine (only declarant) | 421× |
| **Universal feature edit** (e.g., renaming a field used by every machine) | 421 machines | 421 machines | **1× (no reduction by design)** |
| **Frontend renderer plugin update** | varies (silent break risk) | machines using that renderer; schema-version gated | varies + safety improvement |
| **Bespoke-plugin lift for a previously-vanilla machine** | 421 (added to monolith) | 1 (new bespoke feature + manifest line) | 421× |
| **Schema rename inside a universal feature** | 421 + silent renderer break | 421 + explicit fallback rule applied | 1× invalidation but 0× silent break |

Universal-feature-edit class is explicitly **1× by design** — the proposal does not fake reduction. What the proposal delivers is reductions for the **other** classes, making "carve a per-cluster or per-machine feature instead of editing the universal one" the path of least resistance once mechanisms exist.

---

## §2 Design alternatives

v3 keeps v2's 3 alternatives unchanged. A v3 is the recommended variant, refining A v2 per the v3 addendum.

### §2.1 Alternative A v3 — Per-machine manifests + sliced analyzer + operator-diagnostic console signal (recommended)

**Core idea (unchanged from A v2)**: Every one of the 421 machines has an explicit manifest declaring (a) which feature plugins it uses, (b) which round-win rules it uses, (c) **whether the console claims it can diagnose this machine completely** (the new `console_diagnostic_complete` flag — replaces v2's numeric threshold). The analyzer is sliced into `core/` (universal orchestration) + `features/` (opt-in). The per-machine effective analyzer version composes from base + the features the manifest declares.

**Key changes from A v2** (consolidated):

- §5.5 manifest: `console_diagnostic_complete: true|false` (was `fallback_share_pct_max: 0.5`)
- §9: 4-layer integrity check (was 3 layers); Layer 4 NEW catches within-pid attribution drift
- §6: RTP integrity gate code construction → Phase 2 (was Phase 5)
- §5.5 documentation: explicit `inherits_from` justification for variants; eager cascade; `per_mode_overrides` field enumeration

The file tree, Protocol interfaces, manifest schema mechanics, hash composition algorithm, and Phase 1 deliverable list are all preserved from v2 §2.1. Refer to v2 §2.1 for the file tree sketch; v3 changes are in §5.5 / §6 / §9 below.

**Pros (grounded in Wave 1)**:

- Implements addendum §1.5 philosophy — every machine has a manifest; sharing is opt-in via plugin composition.
- Implements addendum §1.4 constraint S **and** addendum v3 §1 operator-diagnostic framing — the console either delivers correct numbers OR an explicit per-machine error with actionable diagnosis hints.
- The new Layer 4 (§9) catches the within-pid mis-attribution case that v2's gate missed (Critic v2 Concern 2 + Q2).
- The `console_diagnostic_complete` flag replaces v2's numeric threshold cleanly — no statistical noise on sampling variance (Critic v2 Concern 2 false-positive cliff goes away).
- Eager-cascade for `inherits_from` aligns with addendum v3 §3 #4 + addendum §1.5 spirit (variants ARE the same machine; updates propagate).
- The Phase 2 RTP-gate construction resolves the Critic v2 Concern 3 / Q4 / Q11 circular dependency.

**Cons (acknowledged)**:

- Manifest accuracy is load-bearing. Operator-side discipline matters more than v2's "if threshold passes, you're safe" framing.
- For 215 of 421 machines without rawdata (per `02 §1`), `console_diagnostic_complete: true` cannot be empirically verified at manifest-author-time. They stay `false` until first rawdata-bearing fleet pull validates them. This is the right safety default per §1.1's "accurate-or-explicitly-error" mandate.
- Per-machine completeness flag flips happen out of scope for v3 (per addendum v3 §2 must-resolve #6: "Per-machine flip to true happens as machine rules are verified clean by some QA pass — out of scope for v3").

**Migration cost estimate**: MEDIUM-HIGH (same as A v2). The Phase 2 RTP-gate-code construction adds a few days to Phase 2 but removes them from Phase 5.

### §2.2 Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar (rejected as in v2)

**Why B remains rejected in v3**: B doesn't satisfy the operator-diagnostic framing from addendum v3 §1. Under B, the console has no mechanism to declare "I cannot diagnose this machine" — it can only emit numbers, with no per-machine completeness signal. B's smallest-change appeal is real, but it's the smallest change that doesn't address the architectural defect. Addendum v3 §1's framing strengthens the v2 rejection.

### §2.3 Alternative C — Full per-machine analyzer plugin tree (rejected as in v2)

**Why C remains rejected in v3**: C eliminates sharing wholesale; addendum §1.5 says "sharing is opt-in via manifest", not "no sharing". Addendum v3 §3 #4 explicitly endorses variant sharing (eager cascade — variants follow underlying because they ARE the same machine). C would force 166 per-variant plugin files, which is exactly the parallel-impl anti-pattern memory `feedback_no_parallel_panel_impl.md` warns against. v3 strengthens v2's rejection.

### §2.4 Comparison table (v3 update)

| Criterion | A v3 (recommended) | B (sidecar) | C (per-machine plugins) |
|---|---|---|---|
| Implements addendum v3 §1 operator-diagnostic framing | YES (§9 reframed; `console_diagnostic_complete` per-machine flag) | NO (no per-machine completeness signal) | PARTIAL (per-machine but no shared completeness mechanism) |
| Implements addendum §1.5 philosophy (every machine potentially unique) | YES (per-machine manifests + variant justification) | NO | OVERSHOOTS (no sharing) |
| Implements addendum §1.4 constraint S | YES (§9 with 4 layers including new Layer 4) | NO | PARTIAL |
| Layer 4 within-pid attribution drift catch (Critic v2 Q2) | YES | NO | PARTIAL |
| `inherits_from` cascade semantics resolved (Critic v2 Concern 4) | YES — eager per addendum v3 §3 #4 | n/a | n/a (no inheritance) |
| Phase 2 RTP-gate dependency (Critic v2 Concern 3) | RESOLVED — gate code in Phase 2 | n/a | n/a |
| `console_diagnostic_complete` per-machine flag (Critic v2 Concern 2 / Q16) | RESOLVED — replaces numeric threshold | NO | NO |
| Solves universal feature-edit blast | NO by design (honest about 1×) | NO | NO |
| Solves schema-rename silence | YES | YES | YES |
| Solves md5 / summary-patch / inference-trigger / schema-fingerprint dup (all 6 of `01 §4`) | YES (Phase 1) | NO | PARTIAL |
| LOC delta estimate | +3,500-4,000 | +250 | +12,000 |
| Migration risk | MEDIUM-HIGH | LOW | HIGH |
| Heavy outlier handling (M260, M279, M250, M21) | Bespoke feature modules | No mechanism | Plugin file per machine |
| Resolves `_unattributed_st*` fallback-bucket silent leak | YES — operator-diagnostic surface per §9 | NO | PARTIAL |

---

## §3 Recommended design — Alternative A v3

**Pick: Alternative A v3** (per-machine manifests + sliced analyzer + operator-diagnostic signal with 4-layer integrity check + per-machine completeness flag + eager variant cascade + Phase 2 gate construction).

**Reasoning** (cited from Wave 1 + addendum + Wave 3 v2 reviews):

1. **A v3 implements addendum v3 §1 operator-diagnostic framing** — the console either emits accurate numbers OR an explicit per-machine error with actionable hints. v2's threshold-gate framing was a misnomer; v3's `console_diagnostic_complete` per-machine declaration is the right abstraction.

2. **A v3 closes the Layer 4 hole identified by Critic v2** — Critic v2 Concern 2 / Q2 showed v2's 3 layers (sum invariant + fallback share + anchor coverage) could pass while real-pid mis-attribution silently corrupted per-SpinType breakdowns. Layer 4 cross-checks `payouts_by_spin_type[label].rows[pid].hit_count` against `payout_ids_top20.rows[pid].spin_type_breakdown[spin_type=N].count` for every (pid, ST) pair. Both must be derived from the same rawdata SpinType field; equality is mechanical. This catches the M31 pid 8 ST=43/ST=44 case (addendum v3 §2 must-resolve #2).

3. **A v3 fixes the Critic v2 Concern 3 phase-ordering contradiction** — by moving the RTP integrity gate code (`fresh_slotlab/rtp_integrity.py` + all 4 layers + manifest integration) to Phase 2, the Phase 2 forcing-function workflow demo for M250 graduation can actually execute (it needs the gate to demonstrate "vanilla manifest fails → bespoke fix → re-runs gate passes"). Phase 5 simplifies to "flip default policy from warn to error for `console_diagnostic_complete: true` machines".

4. **A v3 reuses Wave 3 v2's validated parts** — Validator v2 gave clean APPROVE on hash composition, manifest schema mechanics, Plugin Protocol, file tree, Phase 1 deliverables. v3 keeps all of these. The empirical M274 validation (Layer 1+2+3 PASS against live data) extends naturally to include Layer 4 (which also passes for M274's current state — see §9.2).

5. **A v3 acknowledges variants as a justified exception, not a residual cluster** — `inherits_from` for variants is intentional, not a recovered v1 super-cluster. Variants are the same underlying machine with different user-decision configurations (e.g., a Top Dollar dealer making different picks at the selector screen). Analyzer rules and parsing must be identical between a variant and its underlying because they ARE the same machine. Storage and reports are isolated per variant because user-decision histories differ. `inherits_from` lets variants reuse the underlying's manifest analyzer_features list while preserving per-variant storage paths. This is not "cluster-by-inheritance" because the parser sharing is by definition (variants ARE the same machine), not a similarity assumption. (Detailed paragraph in §5.5.) Per addendum v3 §3 #1 user explicitly authorized this carve-out.

6. **A v3 makes variant cascade eager** — when an underlying's manifest changes, all variants pick up the change immediately. Variants cannot diverge from underlying's parser because they ARE the same machine. Lazy resolution would create silent drift between variant and underlying parser; eager is correct. Per addendum v3 §3 #4 user resolved this.

7. **B is rejected** per §2.2 — doesn't implement operator-diagnostic framing.

8. **C is rejected** per §2.3 — eliminates sharing wholesale.

The remaining sections specify A v3 in detail.

---

## §4 Hash composition rules (unchanged from v2)

v2's algorithm validated cleanly by Wave 3 v2 (Validator §4 cross-product 0 regressions). v3 keeps it unchanged.

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

### §4.2 Per-change-class blast table (unchanged from v2 §1.4 + §4.2)

See §1.4 above. Six change classes; only one (universal-feature edit) stays at 1×, the rest reduce by 12-421×.

### §4.3 Worked examples — invalidation radius

Six examples carried unchanged from v2 §4.3. Example 6 (M250 graduation: vanilla → bespoke) is now executable in Phase 2 because the RTP gate code is built in Phase 2 (per §6 change).

### §4.4 Per-machine config_md5 and code_md5 — virtual side unchanged

Unchanged from v2 §4.4. Out of scope per addendum §3.

### §4.5 Honesty about universal-feature changes

Unchanged from v2 §4.5. The proposal does not claim to reduce blast for universal feature changes; it makes more features non-universal so the path of least resistance changes over time.

### §4.6 Hash composition map (text diagram, unchanged from v2 §4.6)

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

v2's Protocol + manifest mechanics validated by Wave 3 v2. v3 keeps the Protocol unchanged; updates §5.5 manifest schema for `console_diagnostic_complete` flag, variant justification, eager cascade, and `per_mode_overrides` field enumeration.

### §5.1 Three plugin axes (unchanged from v2 §5.1)

| Axis | Existing artifact | v3 contract |
|---|---|---|
| Round-level extraction | `RoundWinRule` ABC at `round_win.py:102` + RULE_REGISTRY at `:423` | Formalized as-is; manifest declares rule_ids |
| Summary-level aggregation | (today: inline in `parse_chunk_response` + `main()`) | NEW `AnalyzerFeature` Protocol with REQUIRES + RTP_CONTRIBUTION flag |
| Frontend rendering | (today: 17 inline renderers; no contract) | NEW renderer registry with explicit fallback rules |
| **[v3 NEW]** Console diagnostic completeness | (today: silent `_unattributed_st<N>` synthesizer) | Per-machine `console_diagnostic_complete` boolean in manifest + 4-layer integrity check per §9 |

### §5.2 `AnalyzerFeature` Protocol (unchanged from v2 §5.2)

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

### §5.3 Frontend renderer registry (unchanged from v2 §5.3)

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

### §5.4 SCHEMA_VERSION bump policy (unchanged from v2 §5.4)

The table is identical to v2's. Pre-commit hook enforcement; fallback test required for any non-trivial bump. Resolves Critic v1 Q7 + §7.8.

### §5.5 Per-machine manifest format — v3 changes

This is where the v3-specific changes concentrate. v2's per-machine-file layout + JSON Schema validation + variant inheritance mechanism is preserved; v3 (a) replaces `fallback_share_pct_max` with `console_diagnostic_complete` boolean; (b) adds explicit variant justification paragraph; (c) documents eager cascade; (d) enumerates fields that support `per_mode_overrides`.

#### §5.5.1 Layout (unchanged from v2)

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

#### §5.5.2 Manifest schema (per-machine file) — v3 form

Changes from v2:
- `rtp_integrity_contract.fallback_share_threshold_pct` REMOVED
- `rtp_integrity_contract.exception_policy` REMOVED
- New top-level field: `console_diagnostic_complete: true | false`
- `rtp_integrity_contract.required_attribution_anchors` retained (for Layer 3 of §9)
- `rtp_integrity_contract.expected_paid_st` + `expected_bonus_st` retained
- Per-mode override enumeration added

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

Notice: no `fallback_share_threshold_pct`, no `exception_policy`. The presence/absence of `console_diagnostic_complete: true` is the single per-machine completeness signal.

#### §5.5.3 `console_diagnostic_complete` semantics

Per addendum v3 §2 must-resolve #6, the field has 2 values:

**`console_diagnostic_complete: true`** — the operator declares "console claims it can diagnose this machine correctly":

- All 4 layers from §9 enforced as **hard errors** if they fail
- Failure blocks the individual machine's report write (the summary write itself may still produce a debug artifact, but the report is marked failed)
- Does NOT block the fleet pull — other machines' reports continue to be produced
- Error message guides the operator per §9.3 format with actionable diagnosis hints

**`console_diagnostic_complete: false`** — used during development of new machine support:

- All 4 layers from §9 are still computed but their failure produces a **warning**, not an error
- Report is still produced + flagged "[INCOMPLETE]" in the summary metadata + visible in the rwtree UI
- Used during development to allow fleet pulls to continue without blocking
- Migration path: when console's rules are verified clean by some QA pass, operator (or QA team) flips the flag from `false` to `true`

**Initial values at Phase 3 cutover** (per addendum v3 §2 must-resolve #6):

> "All 421 machines start `console_diagnostic_complete: false` at Phase 3 cutover. Per-machine flip to `true` happens as machine rules are verified clean by some QA pass (out of scope for v3 — implementation team handles)."

This means Phase 3 ships 421 manifests all set to `false`. Operators get warnings on the dirty fleet but not blocking errors. As the QA team or operator-side process verifies machines clean (M14 has been correct for years; M274 has its bcm_cycle_anchor rule; etc.), they flip individual machines to `true`. The flipping mechanism (who does it, when, what verification) is out of v3 scope.

**Why this is better than v2's numeric threshold**:

- Critic v2 Concern 2 false-positive cliff disappears — there's no statistical threshold to trip on sampling variance.
- Critic v2 Q16 threshold authority question disappears — there's no number to set; it's a binary completeness declaration.
- The flag's semantics align with the operator-diagnostic framing (addendum v3 §1): the console signals "I claim I can diagnose this" or "I am still being built for this machine". No fake-precision threshold.

#### §5.5.4 Variant justification (addendum v3 §3 #1, NEW for v3)

`inherits_from` for variants is intentional and not a recovered v1 super-cluster. The justification:

> **Variants represent the same underlying machine with different user-decision configurations.** A "variant" is created when a machine has a user-facing decision point (e.g., a Top Dollar dealer selector screen, or a wheel-selector mid-spin choice) and the operator wants to analyze the rawdata bucketed by the user's chosen branch separately. The 85 M273 variants (`M273$WheelSelector$0$` through `M273$WheelSelector$84$`) are 85 different selector-instance buckets of the **same machine code** M273.
>
> **Analyzer rules and parsing must be identical between a variant and its underlying.** They run the same paytable, the same SpinType convention, the same round_classification primitives, the same RoundWinRule logic. There is no scenario where M273.json's analyzer_features list should differ from M273$WheelSelector$42$.json's analyzer_features list — they are reading the same rawdata schema from the same machine code.
>
> **Storage and reports MUST be isolated per variant** because user-decision histories differ. Sampling M273$WheelSelector$0$ produces a different rawdata distribution than M273$WheelSelector$1$ because users picked different selector instances. Per-variant storage paths (`rawdata/M273$WheelSelector$0$/mode_<N>/`, `reports/M273$WheelSelector$0$/mode_<N>/`) are unchanged from current convention.
>
> **`inherits_from` lets the variant manifest reuse the underlying's analyzer_features list** by reference, while preserving per-variant storage paths and per-variant `effective_analyzer_version` resolution. The variant file is small (typically the variant-specific identifier only); the analyzer feature set is inherited.
>
> **This is NOT cluster-by-inheritance.** A v1-style super-cluster grouped machines by surface-signal similarity (logicClassNames, schema fingerprint). The inheritance-via-similarity was an assumption that could be wrong (per addendum §1.5: "M250 looked vanilla until investigated"). `inherits_from` for variants is different: the parser sharing is **by definition** because variants ARE the same machine. There is no similarity assumption to be wrong about.

**Operational consequence**: 166 variant manifests are short files referencing their underlying. Updates to the underlying propagate to all variants (see §5.5.5 eager cascade). The "every machine potentially unique" principle from addendum §1.5 still holds for the 393 - 166 = 227 non-variant machines, plus the 26 underlying machines that have variants. The 166 variants are an explicit, well-bounded carve-out.

#### §5.5.5 Variant cascade — eager (addendum v3 §3 #4, NEW for v3)

When an underlying machine's manifest changes (e.g., M273.json adds `cycle_peak_detection` to `analyzer_features`), all variants of that underlying pick up the change immediately. The manifest resolver computes per-variant `effective_analyzer_version` by reading the underlying's current `analyzer_features` list at resolution time.

**Why eager, not lazy**:

- Variants ARE the same machine; their parser cannot drift from the underlying's parser. Lazy resolution would create a state where M273.json says "use feature X" but M273$WheelSelector$42$.json's `effective_analyzer_version` was snapshotted before X was added, so the variant's reports use stale parser logic. This is a silent correctness bug.
- The operator-diagnostic framing (addendum v3 §1) requires accurate signals. A variant whose reports are produced by stale parser logic is a stealth incorrect signal.
- Eager resolution preserves the "variants follow underlying" invariant.

**Hash-composition consequence**: when M273.json's manifest changes, all 86 hashes (1 underlying + 85 variants) flip. This is the same 86-machine cohort fan-out that already exists for upstream `codeSummaryMd5` per `03 §3.4`. v3 accepts this as the correct behavior — variants ARE the same machine, so a parser-affecting change must invalidate all variant reports.

**Blast-radius implication** for the §1.4 table: "Per-cluster feature edit" stays at 12-30 machines for **non-variant** cluster edits (e.g., adding a BCM cleanup rule to all 28-30 BCM machines). For **variant cluster** edits, the variant fanout adds to the count (e.g., editing M273's underlying adds 85 variants). The table's "12-30 machines" range was honest about non-variant clusters; variant cohorts are larger but well-bounded (max ~85 variants per underlying per `02 §4.1` observation 6).

**Operator-side observability**: when M273.json changes, the rwtree UI shows 86 stale rows. The operator can regen them all (per addendum §1.2 clean break, regen from rawdata is acceptable). No silent drift; explicit invalidation.

#### §5.5.6 Fields that support `per_mode_overrides` (addendum v3 §4 — validator v2 doc gap)

Per Validator v2 §3.1 minor gap, v3 enumerates explicitly. The following manifest fields support `per_mode_overrides` (i.e., can be overridden per mode under `per_mode_overrides.<mode_id>.*`):

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

Fields that **do NOT** support `per_mode_overrides`:

- `machine_id`, `manifest_version`, `inherits_from` — identity/structural fields, must be machine-level
- `console_diagnostic_complete` — the completeness declaration is per-machine, not per-mode, because Layer 4 self-consistency operates on rawdata that spans all modes the operator samples. If a machine's mode 2 is "complete" but mode 5 is not, the operator should split into two separate manifest files or upgrade mode 5's machine code to match. The flag is binary per-machine.

**Resolution order**: `per_mode_overrides.<mode>` first applies `_remove` operations to the base list, then applies `_add` operations. Override fields (with `_override` suffix) replace the base field entirely.

#### §5.5.7 Variant-inheriting manifest

Same as v2 §5.5:

```json
{
  "machine_id": "M273$WheelSelector$0$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "console_diagnostic_complete": false,
  "spin_type_convention_override": null,
  "feature_tags_override": null,
  "analyzer_features_override": null
}
```

The variant file is small — references underlying for the heavy fields, declares its own `console_diagnostic_complete`, optionally overrides any inheritable field.

**Note on `console_diagnostic_complete` for variants**: the flag is per-variant, not inherited. A variant can be `console_diagnostic_complete: false` (still being built) even if its underlying is `true`, because variant-specific data may have edge cases the underlying didn't surface. Conversely, an underlying being `false` doesn't force its variants to `false` — though in practice, if the underlying's parser is incomplete, all its variants will fail Layer 1-4 checks for the same reason.

### §5.6 Manifest validation rules — strict (mostly unchanged from v2 §5.6)

Per addendum §1.2 + §1.4 + addendum v3 §1, manifest validation is strict error on drift. Rules:

1. Every machine in `configs/machines.json` MUST have a manifest file. Missing file = error.
2. Every `analyzer_feature` ID MUST correspond to a class in `feature_registry.ALL_FEATURES`. Typo = error.
3. Every `round_win_rule` ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`.
4. REQUIRES dependency satisfaction.
5. Mode coverage: for every mode in `modes_supported`, the resolved per-mode feature set must include all RTP_CONTRIBUTION=True features that the integrity contract requires.
6. `console_diagnostic_complete` MUST be a boolean (not omitted; not other types). Validation: enforce true/false; reject missing or other values.
7. `expected_paid_st` + `expected_bonus_st` non-empty; `required_attribution_anchors` validated at first run (not commit time) against rawdata.
8. **v3 NEW**: if `console_diagnostic_complete: true`, every feature in `analyzer_features` with `RTP_CONTRIBUTION=True` MUST be present.
9. Rawdata sanity check (if rawdata available; 206 of 421 machines):
   - Declared `spin_type_convention.paid` must match observed paid-ST set.
   - If `wild_nudge_classification` is NOT declared but rawdata has ST=36+ReMarks=move, error.
   - If `cycle_peak_detection` is NOT declared but rawdata has `CollectCount` extras, error.
   - If `pay_id_suffix_attribution` is NOT declared but rawdata has line_id values not matching pay_id keys, error.

Note: validation rules 1-8 are commit-time / deploy-time static checks. Rule 9 (rawdata-based) runs at sample time, not commit time.

### §5.7 Feature discovery + missing-feature runtime error (unchanged from v2 §5.7)

`@register` decorator + manual import in `fresh_slotlab/analyzer/features/__init__.py`. `feature_registry.ALL_FEATURES` runtime source of truth. Manifest typo caught at validation; runtime missing-feature raises `RuntimeError` clearly.

### §5.8 In-process monkey-patch path under sliced architecture (unchanged from v2 §5.8)

`pia.main` remains entry point post-slice; thin orchestrator delegating to `analyzer/core/base_pipeline.py`. Monkey-patches attach at same attribute. Phase 1 deliverable 9 codifies 3-style parity test.

### §5.9 Per-machine `round_win_rule` plugin (unchanged from v2 §5.9)

`round_win.py:102` ABC + RULE_REGISTRY unchanged. Manifest references rule_ids.

### §5.10 Plugin lifecycle (unchanged from v2 §5.10)

Adding / deleting / renaming features; historical reports per addendum §1.2 clean-break.

### §5.11 Manifest examples — v3 form

**M1** (vanilla, SC-Vanilla shape):

```json
{
  "machine_id": "M1",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
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

At Phase 3 cutover M1 ships as `false`; after QA verifies M1's parser is clean across modes, the operator flips it to `true`.

**M15** (TopDollar, rule-bearing):

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

**M279** (heavy outlier, BCM+MoveNudge+Wheel; per-mode override demo):

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
    "2": {
      "bcm_target_feature_override": "MoveSpin",
      "required_attribution_anchors_override": ["_bcm_cycle"]
    },
    "5": {
      "bcm_target_feature_override": "MoveSpin",
      "required_attribution_anchors_override": ["_bcm_cycle"]
    },
    "7": {
      "bcm_target_feature_override": "MoveSpin",
      "required_attribution_anchors_override": ["_bcm_cycle"]
    }
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [2, 36],
    "required_attribution_anchors": ["_bcm_cycle", "27905"]
  }
}
```

Mode 1 uses base `required_attribution_anchors` (Wheel-specific with `27905`); modes 2/5/7 override to MoveSpin-specific anchor list. Per Validator v2 §3.1 + addendum v3 §4 doc gap, this demonstrates the `_override` suffix for per-mode contract fields.

**M21** (Buffalo bespoke):

```json
{
  "machine_id": "M21",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
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
    "expected_paid_st": [27],
    "expected_bonus_st": [25],
    "required_attribution_anchors": []
  }
}
```

**M273$WheelSelector$0$** (variant of M273):

```json
{
  "machine_id": "M273$WheelSelector$0$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "console_diagnostic_complete": false,
  "spin_type_convention_override": null,
  "feature_tags_override": null,
  "analyzer_features_override": null
}
```

Variant inherits all parser-affecting fields from M273.json (eager cascade per §5.5.5). The flag is per-variant; the variant can stay `false` even after the underlying is flipped to `true` until its specific user-decision data is verified.

---

## §6 Migration plan — v3 changes

v3 keeps v2's 6 phases. The **change** is moving the RTP integrity gate code construction from Phase 5 to **Phase 2**, which resolves Critic v2 Concerns 3/4/Q4/Q11 (the Phase 2 forcing-function workflow demo cannot execute without the gate it references). Phase 5 simplifies to "flip default policy for `console_diagnostic_complete: true` machines from warn to error".

Per addendum §1.2 (clean break authorized), the migration framework is otherwise identical to v2's. The v3 changes are:
- §6.2 Phase 2 deliverables expanded to include RTP integrity gate code (all 4 layers, warn-only mode)
- §6.5 Phase 5 deliverables compressed: only the policy flip remains; the gate code is already built

### §6.1 Phase 1 — Foundation: extract all 6 duplications + module-global fix + invocation parity (unchanged from v2)

All 12 Phase 1 deliverables from v2 §6 unchanged. Resolves all 5 pre-Phase-1 blockers from `01 §5`. Risk LOW-MEDIUM; 4-6 days; trivial rollback.

### §6.2 Phase 2 — Slice analyzer + 12 known-complex machines as forcing function + RTP integrity gate code (v3 change)

**Goals (updated for v3)**:
- Migrate analyzer monolith from `pia:1-8176` into `fresh_slotlab/analyzer/{core, features}/` tree.
- Introduce `compute_base_analyzer_version` + `compute_feature_hashes`.
- **NEW for v3: build `fresh_slotlab/rtp_integrity.py` with all 4 layers (sum invariant + fallback share + anchor coverage + per-SpinType self-consistency)** — runs in **warn-only mode** for every analyzer run. This is the gate code that v2 deferred to Phase 5; v3 builds it here so Phase 2's forcing-function workflow demo can actually execute.
- **Forcing function (addendum §1.3): 12 known-complex machines onboard cleanly under per-machine plugin path BEFORE the framework is committed**: M21, M260, M268, M279, M274, M113, M11, M250, M108, M65, M67, M120.
- Demonstrate end-to-end the workflow from §4.3 Example 6: "machine X declared vanilla manifest, RTP integrity check fails, we add a per-machine plugin Y, X re-onboards — works without changing the framework". Pick M250 and walk it through.

**Deliverables (v3 updated)**:

1. Carve `core/`: `base_pipeline.py`, `chunk_aggregation.py`, `summary_writer.py`, `schema_gate.py`.

2. Carve universal features: `payouts_by_spin_type.py`, `reel_marginal_by_spin_type.py`, `bankruptcy_simulation.py`, `multiplier_profile.py`.

3. Carve sometimes-applicable features: `bonus_chain_dynamics.py`, `collect_mechanic.py`, `cycle_peak_detection.py`, `wild_nudge_classification.py`, `topdollar_settlement.py`, `wheel_selector_type2.py`, `pay_id_suffix_attribution.py`, `lock_symbol_handling.py`, `lock_lines_handling.py`.

4. Carve the 12 forcing-function bespoke features: `bespoke_m21_buffalo.py`, `bespoke_m260_buffs.py`, `bespoke_m268_credits_symbol.py`, `bespoke_m279_combo.py`, `bespoke_m274_listrewardwheel.py`, `bespoke_m113_expanded.py`, `bespoke_m11_diamond.py`, `bespoke_m250_grid.py`, `bespoke_m108_fillup.py`, `bespoke_m65_collection.py`, `bespoke_m67_open_close.py`, `bespoke_m120_reward_id.py`.

5. **NEW for v3: Build `fresh_slotlab/rtp_integrity.py`** — implements `check_rtp_integrity(summary, manifest) -> RTPIntegrityResult` with all 4 layers per §9. In Phase 2 the gate runs in **warn-only mode** for every analyzer run (regardless of manifest's `console_diagnostic_complete` flag) — every machine's Layer 1-4 results are computed and surfaced as warnings, but no run is blocked. The result struct is attached to the summary at `summary.rtp_integrity_check`. The full §9.3 error format (per-layer + suggested actions) is produced; nothing about the structure is deferred.

6. **NEW for v3 (replaces v2's Phase 5 deliverable 5 demo): Demonstrate Example 6 workflow end-to-end** using the gate that exists in Phase 2:
   - Pick M250 (memory says 100% RTP leak per `feedback_invariant_with_fallback_hides_drift.md`).
   - Write minimal manifest for M250 declaring "I should be BCM" features (without bespoke).
   - Run RTP integrity gate (now exists in Phase 2!) → fails with explicit Layer 2 + Layer 3 errors.
   - Operator reads suggested_actions per §9.3 format.
   - Add `features/bespoke_m250_grid.py` to fix.
   - Update manifest.
   - Re-run RTP gate → all 4 layers pass.
   - Framework not touched. Document the workflow in `docs/feature_onboarding_workflow.md`.

7. `fresh_slotlab/analyzer/versioning.py` with `compute_base_analyzer_version` + `compute_feature_hashes` + `compute_effective_analyzer_version` (per-mode capable per §4.1).

8. `fresh_slotlab/analyzer/feature_registry.py` with explicit `ALL_FEATURES` + topological sort.

9. Per-cluster regression tests — at least one machine per super-cluster shape, plus all 12 forcing-function machines. Byte-identical summary against golden file.

**Rollback**: revert the phase-2 commits. The pre-phase-2 monolith is preserved in git. Per addendum §1.2 no data preservation needed.

**Why Phase 2 forcing function** (addressing Critic v1 Concern 5 + Validator §3.1 + Critic v2 Concern 3 — now resolved):

The 12 known-complex machines are the canaries. If the framework fits them, it fits the long tail. The RTP integrity gate (built in Phase 2 per deliverable 5) is the discovery mechanism for "is the manifest correct for this machine?" — operator runs the gate, sees per-layer + per-machine errors, iterates until clean.

**Cross-dependency RESOLVED**: Phase 2 deliverable 5 (workflow demo) requires the gate (deliverable 5 builds the gate). Phase 2 is self-contained. Phase 5's role is only to flip the default policy from warn to error for machines marked `console_diagnostic_complete: true`.

**Phase 2 risk** (per §6.5): HIGH — slicing the monolith is the biggest lift; building the gate code is new. 10-14 days estimated (v3 adds 2-3 days vs v2's same Phase 2 estimate because the gate code construction lands here now).

### §6.3 Phase 3 — Per-machine manifests + per-feature registry wiring (clean break) (mostly unchanged from v2)

**Goals (v3 minor update)**:
- Land 421 per-machine manifest files (one per machines.json entry).
- All 421 manifests ship with `console_diagnostic_complete: false` at Phase 3 cutover (per addendum v3 §2 must-resolve #6).
- Wire `compute_effective_analyzer_version` to consult manifest per machine, per mode.
- Frontend reads manifest-driven feature list to know which renderers to invoke.
- Clean break from old reports: drop `summary.analyzer_version`'s use as the freshness key.

**Deliverables (v3 minor update)**:

1. Write 421 per-machine manifests in `slot_designer/configs/machine_manifests/<M>.json`. **All ship with `console_diagnostic_complete: false`** initially. The 12 forcing-function machines from Phase 2 + the variant-bearing underlyings get longer manifests; per-mode overrides as needed.

2. `manifest_loader.py` — reads `machine_manifests/<M>.json`, resolves `inherits_from` recursively (per addendum v3 §3 #4 eager), resolves `per_mode_overrides`, returns `EffectiveManifest(machine_id, mode)`.

3. Wire `compute_effective_analyzer_version` to read manifest per (machine, mode).

4. Update analyzer + backend write sites to use effective version (`pia.main()`, `_run_generate_report`, `RunManager.start_run`, `BatchRunManager.finalize_run`).

5. Update `/api/reports/stale-count` at `app.py:5694` to compare per-(machine, mode) `effective_analyzer_version`. No NULL handling (clean break).

6. ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT. NULL = stale (pre-migration rows).

7. Frontend updates (`app.js`, `pure.js`): `_renderRwtreeCell` reads `effective_analyzer_version` for freshness; `_paintAnalysisFromSummary` skips renderers whose `feature_id` isn't in the report's manifest.

8. Manifest validation CLI: `scripts/validate_manifests.py` runs all rules from §5.6.

9. Manifest tooling: `scripts/manifest_lint.py`, `manifest_diff.py`, `manifest_audit.py`.

**Phase 3 risk**: MEDIUM; 4-6 days.

### §6.4 Phase 4 — Frontend renderer registry + schema-version contract enforcement (unchanged from v2)

All 7 Phase 4 deliverables from v2 §6 unchanged. Risk LOW; 2-3 days.

### §6.5 Phase 5 — Flip RTP integrity gate default policy from warn to error (v3 simplified)

**Goals (v3 simplified — most work moved to Phase 2)**:
- Flip the default policy: for machines whose manifest has `console_diagnostic_complete: true`, Layer 1-4 failures become hard errors (block individual machine's report); machines with `console_diagnostic_complete: false` continue warn-only.
- Surface per-machine error states in the UI per §9.3.
- Document the audit deliverable for known-broken machines.

**Deliverables (v3 simplified)**:

1. **Policy flip in `rtp_integrity.py`**: when `manifest.console_diagnostic_complete == true`, layer failures raise; when `== false`, warnings only. This is a configuration change to the gate that was built in Phase 2.

2. Backend surface (mostly already there from Phase 2's gate code; Phase 5 wires the error-vs-warning split):
   - `GET /api/runs/{rid}/integrity` returns the structured result.
   - `POST /api/runs/integrity-check-all` fleet-wide on-demand check.
   - Background job: scheduled fleet pulls run the gate; failures captured in `state/console/console.db.integrity_failures` table.

3. Frontend UI:
   - Per-machine cell in rwtree shows a red badge for `console_diagnostic_complete: true` machines whose gate failed.
   - Per-machine cell shows a yellow "[INCOMPLETE]" badge for `console_diagnostic_complete: false` machines whose gate fired warnings.
   - Click-through opens modal with structured error per §9.3.

4. **Known-broken machines triage** — at Phase 5 deploy time, the operator (or QA team) flips `console_diagnostic_complete` to `true` for machines whose rules are verified clean. The known-broken triage table (§9.7) is illustrative; comprehensive triage is QA's task.

5. **Per-machine error format** (§9.3) finalized as a public contract; documented.

**Rollback**: revert Phase 5 commits. The gate stays in warn-only mode globally (the Phase 2 state). No data loss.

**Why Phase 5 simplified in v3** (per addendum v3 §2 must-resolve #3): the gate code, formats, surfaces, and workflow demonstration all ship in Phase 2 (because Phase 2's forcing-function demo needs the gate to exist). Phase 5 contributes only the policy flip + UI badge + integration into background fleet pulls. Per `console_diagnostic_complete: false` default at Phase 3 cutover, Phase 5 doesn't suddenly produce 22+ red banners — those 22 BCM machines stay `false` (warning) until QA's per-machine flip cleans them up.

**This resolves Critic v2 Concern 5 / Q6** about Phase 5 strict-default-before-Phase-6-audits: the per-machine completeness flag is the de-facto "per-machine audited flag" Critic v2 §7.3 suggested; flipping happens out of scope for v3 (per QA team handles).

**Phase 5 risk**: LOW-MEDIUM; 2-3 days. (Down from v2's 5-7 days because most work moved to Phase 2.)

### §6.6 Phase 6 — (Optional / out-of-scope) Retro-fit + consolidation (mostly unchanged from v2)

Optional per v2 §6.6. Phase 6 deliverables:

1. Optional consolidation of `machine_round_win_rules.json` into per-machine manifests.
2. Document architectural workflow in `slot_designer/ARCHITECTURE.md` + `docs/ARCH_TEAM_PROCESS.md`.
3. Audit medium outliers (~30 machines per `02 §5.2`) — write manifests for them; run RTP integrity; flip `console_diagnostic_complete: true` for verified-clean ones.

Risk LOW; 3-5 days.

### §6.7 Phase summary table (v3 updated)

| Phase | Risk | Days est. | Schema change | Rollback simplicity |
|---|---|---|---|---|
| 1 (dedup + globals + 5 mapper blockers) | LOW-MEDIUM | 4-6 | None | Trivial revert |
| 2 (slice analyzer + 12 forcing-function machines + **RTP integrity gate code v3**) | HIGH | 12-16 (v2 was 10-14; +2 for gate code) | Per-feature SCHEMA_VERSION; effective_analyzer_version field; `summary.rtp_integrity_check` field | Per-feature revert |
| 3 (manifests + clean-break wiring; all 421 ship `console_diagnostic_complete: false`) | MEDIUM | 4-6 | Manifest files; new DB col | Manifest ignored on rollback |
| 4 (frontend registry + SCHEMA_VERSION enforcement) | LOW | 2-3 | None | Trivial revert |
| 5 (**flip default policy for `console_diagnostic_complete: true` machines** + UI badges) | LOW-MEDIUM | 2-3 (v2 was 5-7; −3 because gate code in Phase 2) | New `integrity_failures` DB table; new badge UI | Policy flip reverts globally |
| 6 (optional retro-fit + consolidation + medium outlier audit) | LOW | 3-5 | None | Optional throughout |

Total: ~27-39 dev days (sequential). Roughly v2's same total (28-41 days); v3 redistributes 2-3 days from Phase 5 to Phase 2.

### §6.8 Migration constraint compliance (v3 updated)

| Constraint | How honored by v3 plan |
|---|---|
| **00 §5.1** Backward-compat for 393 machines' reports | Per addendum §1.2 clean-break authorization, relaxed. Operators regen from rawdata. |
| **00 §5.2** Prod console (8877) never breaks | Each phase has rollback; Phase 2 verified against 12 forcing-function machines BEFORE commit. |
| **00 §5.3** Virtual reuses prod code | Phase 1 removes 6 dups; Phase 2's features shared. |
| **00 §5.4** New machine = O(1) hash | Phase 3 manifests + Phase 2's bespoke pattern. Universal-feature changes still 1× per §1.4. |
| **00 §5.5** Rollback per phase | Documented per phase. |
| **00 §5.6** No silent data loss | Phase 2 RTP integrity gate (4 layers including Layer 4) makes silent loss explicit error or warning per `console_diagnostic_complete`. |
| **Addendum §1.4** RTP integrity hard constraint S | Phase 2 gate + Phase 5 policy flip + §9 reframed per addendum v3 §1. |
| **Addendum §1.5** Every machine potentially unique | Phase 3 per-machine manifests; eager variant cascade per §5.5.5. |
| **Addendum v3 §1** Operator-diagnostic framing | §9 entirely rewritten; `console_diagnostic_complete` per-machine flag (§5.5.3); §1 problem statement rewritten. |
| **Addendum v3 §2 must-resolve #2** Layer 4 within-pid attribution | §9.2 Layer 4 added. |
| **Addendum v3 §2 must-resolve #3** Phase 2/5 ordering | §6.2 + §6.5 resolved. |
| **Addendum v3 §2 must-resolve #6** Per-machine completeness flag | §5.5.3 replaces v2 numeric threshold. |
| **Addendum v3 §3 #1** `inherits_from` variant justification | §5.5.4 dedicated paragraph. |
| **Addendum v3 §3 #4** Variant cascade eager | §5.5.5. |
| **Addendum v3 §4** Validator v2 doc gaps | §5.5.6 + §9.7 illustrative-not-exhaustive marker. |

---

## §7 Open questions for Critic v3

Per addendum v3 §7, critic v3 only — validator v2 already APPROVE. v3 reduces the v2 open-question count from 4 to **3** because addendum v3 resolves several by user clarification.

### §7.1 Phase 2 gate code maturity for v3 forcing-function demo

§6.2 deliverable 5 builds the RTP integrity gate in Phase 2 (all 4 layers in warn-only). Deliverable 6 demonstrates the M250 graduation workflow end-to-end. **Critic v3 should verify**: is "build the gate AND the demo in Phase 2" feasible in the revised 12-16 day Phase 2 window? Specifically, is the gate's Layer 4 (cross-checking `payouts_by_spin_type` against `payout_ids_top20.spin_type_breakdown`) implementable without already-extracted features (the very features being carved out in Phase 2)? Tentative answer: Layer 4 reads two fields from the final summary JSON; both are produced by features that exist by Phase 2 deliverable 2 (universal features). So Layer 4 implementation is independent of Phase 2's feature-carving order. Critic v3 should sanity-check this dependency direction.

### §7.2 `console_diagnostic_complete` flip authority + per-mode flag granularity

v3 §5.5.3 says all 421 machines start `console_diagnostic_complete: false` at Phase 3 cutover; per-machine flip to `true` happens out of scope (QA team). v3 §5.5.6 explicitly says the flag is binary per-machine (not per-mode). **Critic v3 should verify**: for a machine where mode 1 is monitorable and clean but mode 5 is RTP-not-monitorable per memory `user_testing_machine.md`, does the binary flag work? Tentative answer: yes — the flag means "console claims it can diagnose this machine". Mode-5 not-monitorable is a measurement-side concern (sampling can't get reliable RTP from mode 5), not a parser-side concern (console's logic for mode 5 parsing may still be correct). The flag is about parser correctness. If mode 5's parser is correct but mode 5's RTP is sampling-noisy, that's the operator's concern at the report level, not the gate's concern at the integrity level. Critic v3 should verify this framing holds.

### §7.3 Layer 4 false-positive sources

Layer 4 compares `payouts_by_spin_type[label].rows[pid].hit_count` against `payout_ids_top20.rows[pid].spin_type_breakdown[spin_type=N].count`. Both fields are derived from the same rawdata SpinType field via the same `payouts_by_spin_type` feature. Mechanical equality should hold by construction. **Critic v3 should verify**: is there any analyzer path where these two derived values could legitimately differ (e.g., one filters zero-hit pids while the other doesn't, one uses session-bonus aggregation while the other uses paid-only, etc.)? Tentative answer: per v2 §10 + addendum v3 §2 reframe, both values are computed by the same feature's `extract`/`reduce`/`emit` path. The label and breakdown axes are different presentation slices of the same accumulator. If they differ, it's a bug in the feature's emit code that should be caught by Layer 4. But Critic v3 should sanity-check whether there's a legitimate filtering or rounding asymmetry that would cause a "false positive" mismatch.

---

## §8 Out of scope (refined for v3)

§8.1-§8.12 unchanged from v2 §8. Plus one v3-specific note:

### §8.13 `console_diagnostic_complete` flip mechanism + QA workflow

The QA pass that verifies a machine's rules are clean and flips `console_diagnostic_complete` from `false` to `true` is **out of v3 scope**. Per addendum v3 §2 must-resolve #6 explicit: "Per-machine flip to true happens as machine rules are verified clean by some QA pass (out of scope for v3 — implementation team handles)."

This includes:
- Which team owns flip decisions (QA / operator / slot-* team / arch team)
- What verification triggers a flip (rawdata sweep across modes; cross-mode self-consistency; cross-machine reference comparison)
- Workflow for batch flipping (e.g., flip all 28 BCM machines after their cycle_peak_detection rules are verified clean)
- Tooling for the flip workflow

These are operational concerns for the implementation team. v3 specifies only the manifest field semantics and the gate behavior under `true`/`false`.

---

## §9 Operator diagnostic signal — Console's RTP integrity output (REWRITTEN per addendum v3 §1 + §2 must-resolve #2 + #6)

This section is entirely rewritten from v2 §9. The v2 framing was "RTP integrity enforcement as internal correctness check, 3 layers + numeric threshold". The v3 framing per addendum v3 §1 is **"operator diagnostic signal — the console tells the operator when it cannot reliably analyze a machine, with actionable diagnosis hints"**.

### §9.1 Purpose

The console exists to help the operator (策划) find issues in production machine configurations they themselves wrote. Production machines faithfully execute the operator's configuration. Rawdata reflects that configuration. The console's job is to analyze rawdata correctly and tell the operator whether the result matches intent.

**When the console cannot reliably analyze a machine, it must surface that to the operator with actionable diagnosis hints — not silently fall back to wrong numbers.**

This section specifies the 4-layer check that determines whether the console can analyze a machine reliably. Failures from any layer produce structured per-machine errors (or warnings, per the `console_diagnostic_complete` flag). The check is mandatory on every analyzer run for every (machine, mode) combination.

Memory `feedback_invariant_with_fallback_hides_drift.md` documents the failure mode: "55 of 117 cached BCM (machine, mode) pairs have >0.5% RTP falling into the `_unattributed_st<N>` fallback bucket". M274 had 4.87% silently misattributed before the `bcm_cycle_anchor_m274` rule landed. M250 has 100% silently misattributed today. The 4-layer check makes these explicit signals rather than silent leaks.

Memory `feedback_no_silent_swallow.md` documents the broader principle: any best-effort post-hook's outcome must persist to disk. The integrity check result is persisted per-run (in DB + in `summary.rtp_integrity_check`); never silently swallowed.

### §9.2 The 4-layer integrity check

For every (machine, mode) analyzer run, the gate computes 4 layers and produces a structured result. The 4 layers:

#### Layer 1 — Hard invariant (kept from v2)

```
sum(payout_id_win[pid] for all pid) == chunk_win  (across all chunks)
```

If this fails, the analyzer's arithmetic is wrong. Today's analyzer already raises on Layer 1 failure (via the universal `_unattributed_*` fallback synthesizer — see Layer 2). Layer 1 catches pure arithmetic / accumulator bugs.

#### Layer 2 — Fallback-bucket non-existence (changed from v2's threshold)

v2's Layer 2 was: `fallback_share_pct ≤ threshold_pct`. v3 removes the numeric threshold per addendum v3 §2 must-resolve #6. The v3 Layer 2 is:

```
No payout_id starts with "_unattributed_", "_other", or any reserved fallback prefix.
```

In other words, **the existence of any fallback-bucket row** is the signal that the console couldn't attribute some win to a real pay_id. Per addendum v3 §1's operator-diagnostic framing, this is the moment to tell the operator "I couldn't analyze this completely — investigate".

There is no statistical threshold. If `_unattributed_st139` shows up with even 1 hit, Layer 2 fires. This eliminates Critic v2 Concern 2 (sampling-noise false positives don't matter because fallback buckets are not produced by sampling noise — they're produced by parser-rule gaps).

The reserved fallback prefix list is: `_unattributed_`, `_other`, `_default`, `_misc`. Any pay_id starting with one of these triggers Layer 2.

#### Layer 3 — Attribution-anchor coverage (kept from v2)

Per manifest, every machine declares `required_attribution_anchors` — a list of pay_ids that MUST appear in the summary (with > 0 hits) if the machine's mechanic is functioning correctly. Examples:

- M274's manifest requires `["_bcm_cycle", "5801"]` — both must have hits.
- M15's manifest requires `["666"]` (TopDollar trigger pid).
- A vanilla machine like M1 may have `[]` (no required anchors).

If any required anchor has 0 hits, Layer 3 fires (with explicit "expected anchor X not found").

#### Layer 4 — Per-SpinType attribution self-consistency (NEW for v3 per addendum v3 §2 must-resolve #2)

v2's 3 layers passed in the case where a pid's total RTP was correct AND no fallback bucket existed AND the required anchor was present, but the per-SpinType breakdown of that pid was silently wrong. Example: pid 8 fires 33,167 times — rawdata shows 22,370 in ST=43 (paid) + 10,797 in ST=44 (free). If the console's parser logic mistakenly attributes all 33,167 to ST=43, the total stays correct (Layer 1 OK), no fallback bucket (Layer 2 OK), required anchor present (Layer 3 OK) — but the per-SpinType breakdown is wrong.

Layer 4 catches this by cross-checking two derived summary fields against each other:

```
For every pay_id (pid) whose summary includes a spin_type_breakdown sub-block:
  For every spin_type N in pid's spin_type_breakdown:
    Let A = payouts_by_spin_type["ST{N}_<label>"].rows[pid].hit_count
    Let B = payout_ids_top20.rows[pid].spin_type_breakdown[spin_type=N].count
    Assert A == B
```

Both A and B are derived from the same rawdata's SpinType field via the same `payouts_by_spin_type` feature. Equality is mechanical — they're two presentation slices of the same accumulator. If they differ, it's a parser bug or rule-mapping bug that's been silently corrupting per-SpinType breakdowns.

**Failure example error message**:

> "Per-ST attribution inconsistent for pay_id 8: `payouts_by_spin_type` says 22370 in ST43 / 10797 in ST44; `payout_ids_top20.spin_type_breakdown` says 33167 in ST43 / 0 in ST44. Likely cause: round_classification rule for ST attribution missing for this machine. Investigate."

The gate emits one such error message per (pid, ST) mismatch. The operator reads them and investigates per-machine.

#### Summary: combined check structure

```python
@dataclass
class RTPIntegrityResult:
    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool
    layer1_error: str | None
    layer2_no_fallback_buckets_ok: bool       # v3: changed from threshold
    layer2_fallback_buckets_found: list[str]   # v3: list of fallback pids found
    layer3_anchors_ok: bool
    layer3_missing_anchors: list[str]
    layer4_per_st_consistency_ok: bool         # v3 NEW
    layer4_inconsistencies: list[dict]         # v3 NEW; one entry per (pid, ST) mismatch
    summary_message: str
    suggested_actions: list[str]
    completeness_declared: bool                # mirrors manifest.console_diagnostic_complete
```

A machine **passes** only if all 4 layers pass.

A failing machine produces a structured error per §9.3. The `completeness_declared` field mirrors the manifest's `console_diagnostic_complete` so the surface layer can route to error vs warning correctly per §5.5.3.

### §9.3 Per-machine error format

For a failing machine, the error is structured per layer and surfaces actionably. Each failed layer produces:

1. **Which layer failed** (Layer 1 / 2 / 3 / 4)
2. **Relevant rawdata excerpt or count** (e.g., for Layer 2: the fallback pids found; for Layer 4: the specific (pid, ST) mismatch)
3. **Guidance**: actionable hints in the format

> "Possible causes: (a) operator misconfigured something / (b) console rule for X needs update / (c) data corruption. Investigate."

#### JSON error format (v3)

```json
{
  "machine": "M250",
  "mode": 1,
  "passed": false,
  "completeness_declared": true,
  "layer1_invariant_ok": true,
  "layer2_no_fallback_buckets_ok": false,
  "layer2_fallback_buckets_found": ["_unattributed_st139", "_unattributed_st2"],
  "layer3_anchors_ok": false,
  "layer3_missing_anchors": ["_bcm_cycle"],
  "layer4_per_st_consistency_ok": true,
  "layer4_inconsistencies": [],
  "summary_message": "M250 mode 1 failed integrity: Layer 2 fallback buckets present (_unattributed_st139 with 1247 hits / 100.0% RTP, _unattributed_st2 with 8 hits / 0.01% RTP); Layer 3 missing anchor `_bcm_cycle`.",
  "suggested_actions": [
    "Manifest declares cycle_peak_detection feature but no bcm_cycle_anchor rule. Possible causes: (a) operator misconfigured paytable for this machine / (b) console rule for BCM cycle peak attribution needs update (rule analogous to bcm_cycle_anchor_m274) / (c) M250's 20-reel grid mechanic may need bespoke handling. Investigate.",
    "Likely fix: enable bcm_cycle_anchor rule (round_win_rules: [\"bcm_cycle_anchor_m250\"]) and define the per-machine rule.",
    "Alternatively: add features/bespoke_m250_grid.py to handle the 20-reel grid mechanic; declare in manifest.",
    "See memory/feedback_invariant_with_fallback_hides_drift.md for similar machines."
  ]
}
```

#### Layer 4 failure example

```json
{
  "machine": "M31_hypothetical",
  "mode": 1,
  "passed": false,
  "completeness_declared": true,
  "layer1_invariant_ok": true,
  "layer2_no_fallback_buckets_ok": true,
  "layer2_fallback_buckets_found": [],
  "layer3_anchors_ok": true,
  "layer3_missing_anchors": [],
  "layer4_per_st_consistency_ok": false,
  "layer4_inconsistencies": [
    {
      "pay_id": 8,
      "spin_type": 43,
      "value_in_payouts_by_spin_type": 22370,
      "value_in_spin_type_breakdown": 33167,
      "difference": 10797
    },
    {
      "pay_id": 8,
      "spin_type": 44,
      "value_in_payouts_by_spin_type": 10797,
      "value_in_spin_type_breakdown": 0,
      "difference": 10797
    }
  ],
  "summary_message": "M31_hypothetical mode 1 failed integrity: Layer 4 per-SpinType attribution inconsistent for pay_id 8. payouts_by_spin_type says 22370 in ST43 / 10797 in ST44 (total 33167); payout_ids_top20.spin_type_breakdown says 33167 in ST43 / 0 in ST44. The 10797 free-spin hits are missing from the ST44 sub-block of payout_ids_top20.",
  "suggested_actions": [
    "Possible causes: (a) operator misconfigured the trigger-session pattern for this machine / (b) console rule for ST44 (free spin) attribution missing — round_classification's attribute_lines_to_pay_ids may not be picking up the free-spin ST routing / (c) data corruption in chunk SpinType field. Investigate.",
    "Likely fix: review the trigger_session_pattern declaration in the manifest; verify round_classification rule for ST=44 routes free-spin pay_ids correctly.",
    "Reference machines with similar ST=44 free-spin attribution: M14 mode 1, M120 mode 1."
  ]
}
```

#### Human-readable string (CLI / log output)

```
[ERROR] M250 mode 1: console integrity FAILED (console_diagnostic_complete=true)
  Layer 1 (sum invariant):           OK
  Layer 2 (no fallback buckets):     FAIL — found _unattributed_st139 (1247 hits / 100.0% RTP),
                                              _unattributed_st2 (8 hits / 0.01% RTP)
  Layer 3 (anchor coverage):         FAIL — missing required anchor `_bcm_cycle`
  Layer 4 (per-ST self-consistency): OK
  Summary: This machine's manifest declares it should have BCM cycle attribution,
           but the analyzer's current rule set is not producing the _bcm_cycle anchor.
           Possible causes: (a) operator misconfig / (b) console rule update needed / (c) data corruption.
  Suggested fix: see suggested_actions[]
```

```
[WARN] M250 mode 1: console integrity warnings (console_diagnostic_complete=false)
  Layer 1 (sum invariant):           OK
  Layer 2 (no fallback buckets):     WARN — found _unattributed_st139 (1247 hits / 100.0% RTP)
  Layer 3 (anchor coverage):         WARN — missing required anchor `_bcm_cycle`
  Layer 4 (per-ST self-consistency): OK
  Report produced with [INCOMPLETE] flag. Operator: this machine's manifest is still being built.
```

### §9.4 How the error is surfaced to the operator

**Backend**:

- Every `pia.main` invocation runs `check_rtp_integrity` (Phase 2 deliverable 5) and attaches result to `summary.rtp_integrity_check`.
- When `completeness_declared == true` and any layer fails: the analyzer returns non-zero exit code (after writing summary). `RunManager.start_run` catches the exit code; the `runs` row is marked `status='failed'` with `failure_reason='rtp_integrity'`.
- When `completeness_declared == false`: the analyzer logs warning to stderr but returns success exit code; the `runs` row is marked `status='completed'` with a flag indicating warnings are present.
- Backend exposes `GET /api/runs/{rid}/integrity` returning structured result.
- Fleet-wide endpoint `GET /api/integrity/status` returns roll-up of all failing or warning machines.

**UI** (Phase 4 + Phase 5 wiring):

- Per-machine rwtree cell shows:
  - Red border + "Integrity failed" badge for `completeness_declared == true` machines with failing layers.
  - Yellow border + "[INCOMPLETE]" badge for `completeness_declared == false` machines with warning layers.
  - Normal cell for machines passing all layers.
- Click-through opens modal with full structured error message + suggested actions.
- Fleet dashboard tile: "X machines have integrity failures; Y machines have integrity warnings [INCOMPLETE]".

**CLI / log**:

- `pia.main` prints the human-readable string to stderr on failure or warning per §9.3.
- Batch-run worker propagates the error per job item; the batch result includes per-item integrity status.

### §9.5 When the check runs

| Trigger | When integrity check runs |
|---|---|
| Live sampling via `POST /api/runs` | At end-of-run, before summary write |
| In-process replay via `POST /api/rawdata/{m}/generate-report` | After `pia.main()` returns |
| Batch generate-report `POST /api/rawdata/batch-generate-report` | Per item, after each subprocess run |
| Fleet-wide cron pull (e.g., nightly refresh) | Per machine after analyzer completes |
| On-demand fleet check `POST /api/runs/integrity-check-all` | Iterates all (machine, mode) with recent reports |
| Manifest validation `scripts/validate_manifests.py` | Static-only checks (no rawdata); flags machines whose declared `console_diagnostic_complete: true` is set without all RTP_CONTRIBUTION=True features in `analyzer_features` |

The integrity check is **mandatory** — there is no flag to disable it globally. The per-machine knob is the manifest's `console_diagnostic_complete` boolean per §5.5.3.

### §9.6 Interaction with manifest validation

When the manifest declares `analyzer_features = [F1, F2, F3]` and the integrity check fails:

- **If Layer 2 fails (fallback buckets present)**: the manifest claims F1/F2/F3 cover this machine's mechanics, but the parser produced `_unattributed_*` rows. Operator's job: either (a) update manifest to declare additional features (e.g., the bespoke one), (b) fix the existing features to handle this machine, or (c) keep `console_diagnostic_complete: false` until QA verifies clean.

- **If Layer 3 fails (missing anchors)**: the manifest claims anchor X should appear, but it didn't. Usually means the round_win_rule that synthesizes X isn't applied (e.g., M274's `_bcm_cycle` anchor requires `bcm_cycle_anchor_m274` rule).

- **If Layer 4 fails (per-ST self-consistency)**: the manifest's features produce inconsistent per-SpinType breakdowns for some pid. The parser logic has a routing bug. Operator: investigate the trigger-session pattern declaration and round_classification rules.

The check IS the enforcement mechanism for manifest correctness. A manifest is "correct" iff the integrity check passes for that machine on representative rawdata. The check is the proof; the manifest is the claim.

### §9.7 Known-broken machines triage — **Illustrative, not exhaustive — comprehensive list maintained by QA team** (per addendum v3 §4 + validator v2 doc gap)

The following machines are known-broken today per memory `feedback_invariant_with_fallback_hides_drift.md` and other empirical observations. **This table is illustrative of the failure modes; it is NOT an exhaustive list. The comprehensive triage list is maintained by the QA team during the Phase 5 default-policy flip rollout.**

| Machine | Mode | Symptom | Failure layer (under v3 gate) | Phase 5 / QA action |
|---|---|---|---|---|
| M250 | 1 | ~100% RTP in `_unattributed_st139` | Layer 2 + Layer 3 (missing `_bcm_cycle`) | Bespoke feature `bespoke_m250_grid.py` already in Phase 2 forcing function. Flip flag after verified. |
| M268 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m268_credits_symbol.py` in Phase 2. Flip after verified. |
| M260 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m260_buffs.py` in Phase 2. Flip after verified. |
| M264 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Enable `cycle_peak_detection` in manifest; verify integrity passes. |
| M163 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M147 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M274 | 1 | (resolved via `bcm_cycle_anchor_m274` rule) | All 4 layers PASS as of 2026-05-13 | Confirmation only; ready for `console_diagnostic_complete: true` after QA validates other modes. |
| M99 / M112 | (varied) | Sub-round dedup defect (different class from BCM) | Likely Layer 1 (sum invariant) or Layer 4 | Add dedup rule per `lock_symbol_handling` feature; verify. |
| ~16-21 additional BCM machines | (varied) | 0.5-35% fallback share | Layer 2 | QA team's fleet sweep during Phase 5 rollout identifies them. |

The QA team's comprehensive triage workflow is out of v3 scope per §8.13. v3 provides the gate mechanism and the structured error format; the per-machine investigation + per-machine flag flip is operator/QA work.

### §9.8 Memory cross-reference

The integrity check directly implements lessons from memory:

- `feedback_invariant_with_fallback_hides_drift.md`: "兜底合成器（`_unattributed_st<N>` / `_unattributed_residual` 这类垃圾桶 label）应当被设计成 **告警信号** 而非 **静默关账机制**." v3 makes this concrete with Layer 2 (any fallback bucket fires a signal) and Layer 4 (catches within-pid mis-attribution that previously slipped through).
- `feedback_no_silent_swallow.md`: any best-effort post-hook's outcome must persist to disk. The integrity check result is persisted per-run (DB + summary); never silently swallowed.
- Addendum v3 §1: "Console must analyze rawdata correctly so its diagnostic signals are trustworthy. When console 'can't diagnose' a machine, it must say so explicitly with actionable error message — NOT silently fall back to wrong numbers." v3 §9 is the architectural implementation of this principle.

---

## §10 Resolution map — addendum v3 changes + Critic v2 remaining blockers

### §10.1 Critic v2's 6 remaining blockers — where v3 addresses each

| # | Critic v2 blocker | Resolution per addendum v3 / v3 §x |
|---|---|---|
| 1 | `inherits_from` reintroduces clustering | **Addendum v3 §3 #1**: kept by user decision; v3 §5.5.4 adds explicit variant justification paragraph (parser-sharing is by definition, not similarity assumption). |
| 2 | RTP integrity gate has 2 holes: (a) sampling-noise false positives on threshold + (b) doesn't catch within-pid attribution drift | **(a) resolved by addendum v3 §2 must-resolve #6** (replace numeric threshold with `console_diagnostic_complete` per-machine flag → no threshold to trip). **(b) resolved by addendum v3 §2 must-resolve #2** (new Layer 4 per-SpinType self-consistency check → v3 §9.2). |
| 3 | Phase 2 forcing-function demo references Phase 5 gate | **Resolved by addendum v3 §2 must-resolve #3**: v3 §6.2 deliverable 5 builds the gate code in Phase 2. v3 §6.5 simplified to policy-flip only. |
| 4 | `inherits_from` cascade semantics | **Resolved by addendum v3 §3 #4**: v3 §5.5.5 documents eager cascade. Variants follow underlying because they ARE the same machine. |
| 5 | Phase 5 strict default ships before Phase 6 BCM audits | **Resolved by addendum v3 §2 must-resolve #6 + §3 #5**: all 421 machines ship `console_diagnostic_complete: false` at Phase 3 cutover; Phase 5 policy flip only affects machines that QA has verified clean. The 22+ today-broken BCM machines stay `false` (warning) until rules are added. No day-1 red banners. |
| 6 | Threshold authority | **Resolved by addendum v3 §2 must-resolve #6**: numeric threshold removed; per-machine completeness flag replaces it. No authority question — the operator (via QA team workflow per §8.13) flips per-machine. |

### §10.2 Validator v2 2 minor doc gaps

| Gap | v3 fix |
|---|---|
| §5.5 enumerate which manifest fields support `per_mode_overrides` | v3 §5.5.6 explicit table. |
| §9.7 mark known-broken triage table as "illustrative, not exhaustive" | v3 §9.7 prefix: "Illustrative, not exhaustive — comprehensive list maintained by QA team". |

### §10.3 Items NOT in v3's scope (per addendum v3 §3)

- `inherits_from` for variants — kept; algorithmic addressed; 1-paragraph justification added (§5.5.4).
- Variant cascade semantics — eager; addressed (§5.5.5).
- Phase 5 strict default before Phase 6 BCM audits — user explicitly accepted ("问题不大"); `console_diagnostic_complete: false` mechanism protects 22+ today-broken machines.

---

## §11 Closing

v3 is a focused revision of v2 that integrates addendum v3 §1 (operator-diagnostic framing), addendum v3 §2 must-resolves #2/#3/#6 (Layer 4 / Phase 2 gate / completeness flag), and addendum v3 §4 (validator doc gaps). The proposal preserves v2's validated parts (hash composition, manifest schema baseline, Plugin Protocol, 6-phase migration framework) and rewrites only the sections where the operator-diagnostic framing or the structural must-resolves demanded changes.

Expected next step: critic v3 verifies that the 3 must-resolves are addressed cleanly. Per addendum v3 §7, validator v3 is not required unless critic flags case-level concerns.

---

```
arch-designer complete.
- Version: v3
- Alternatives explored: 3 (A v3 recommended; B rejected per addendum v3 §1 non-viability; C rejected per addendum §1.5 overshoot + addendum v3 §3 variant carve-out)
- Recommended: Alternative A v3 — per-machine manifests + sliced analyzer + operator-diagnostic 4-layer integrity check + `console_diagnostic_complete` per-machine flag + eager variant cascade
- Hash composition: per-(machine, mode) effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12] (unchanged from v2)
- Migration phases: 6 (1 foundation+globals+5-blockers, 2 slice-analyzer+12-forcing-function+RTP-gate-code-construction, 3 per-machine-manifests-clean-break-all-incomplete, 4 frontend-registry+SCHEMA_VERSION-enforcement, 5 default-policy-flip-for-complete-machines, 6 optional-consolidation)
- Addendum v3 must-resolves addressed: 3/3 (#2 Layer 4 / #3 Phase 2/5 reordering / #6 completeness flag)
- Addendum v3 minor doc gaps addressed: 2/2 (§5.5 per_mode_overrides enumeration / §9.7 illustrative-not-exhaustive)
- Critic v2 6 blockers status: 3 resolved by user clarification (addendum v3 §3 #1 #4 #5); 3 addressed structurally in v3 (Concerns 2 / 3 / 5+6 via must-resolves #2 #3 #6)
- Validator v2 status: APPROVE — no algorithmic changes that affect Wave 3 v2 case walkthroughs
- New section: §9 entirely rewritten with operator-diagnostic framing + Layer 4 added
- Removed: `fallback_share_pct_max` numeric threshold; `exception_policy` per-machine field
- Added: `console_diagnostic_complete: true|false` per-machine flag; Layer 4 per-SpinType self-consistency check; eager variant cascade documentation; per_mode_overrides field enumeration
- Out-of-scope items: 13 (12 from v2 + §8.13 console_diagnostic_complete flip mechanism + QA workflow)
- Open questions for Critic v3: 3 (down from v2's 4 — addendum v3 resolved #1, kept #3 [renamed], added 2 v3-specific)
- Output: session_artifacts/_arch/04_architecture_proposal_v3.md
```
